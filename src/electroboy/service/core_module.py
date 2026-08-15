"""Core service module contribution."""

from __future__ import annotations

from .registry import RouteDefinition, ServiceModule


def _route(method: str, path: str, handler_name: str) -> RouteDefinition:
    return RouteDefinition(method, path, "core", handler_name)


def module() -> ServiceModule:
    """Return the module that exposes the service shell and workflow registry."""

    return ServiceModule(
        id="core",
        label="Service Core",
        routes=(
            _route("GET", "/", "index"),
            _route("GET", "/api/health", "health"),
            _route("POST", "/api/contexts", "create_context"),
            _route("GET", "/api/project", "project_payload"),
            _route("POST", "/api/project/open", "open_project"),
            _route("POST", "/api/project/new", "create_project"),
            _route("POST", "/api/project/deactivate", "deactivate_project"),
            _route("GET", "/api/workflow", "workflow_payload"),
            _route("POST", "/api/workflow/stage", "set_workflow_stage"),
            _route("GET", "/api/workflows/config", "workflow_config"),
            _route(
                "POST",
                "/api/workflows/config/workflows",
                "add_configured_workflow",
            ),
        ),
        capabilities=frozenset({"context", "project", "workflow-registry"}),
        state_namespace="core",
    )
