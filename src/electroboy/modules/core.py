"""Core service runtime module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="core",
        label="Service Core",
        routes=(
            route("GET", "/", "core", "index"),
            route("GET", "/api/health", "core", "health"),
            route("POST", "/api/contexts", "core", "create_context"),
            route("GET", "/api/project", "core", "project_payload"),
            route("POST", "/api/project/open", "core", "open_project"),
            route("POST", "/api/project/new", "core", "create_project"),
            route("POST", "/api/project/deactivate", "core", "deactivate_project"),
            route("GET", "/api/workflow", "core", "workflow_payload"),
            route("POST", "/api/workflow/stage", "core", "set_workflow_stage"),
            route("GET", "/api/workflows/config", "core", "workflow_config"),
            route(
                "POST",
                "/api/workflows/config/workflows",
                "core",
                "add_configured_workflow",
            ),
        ),
        capabilities=frozenset({"context", "project", "workflow-registry"}),
        state_namespace="core",
    )

