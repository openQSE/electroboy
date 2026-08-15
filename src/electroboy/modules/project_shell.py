"""Project shell capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="project_shell",
        label="Project Shell",
        routes=(
            route("POST", "/api/shell/start", "project_shell", "start"),
            route("POST", "/api/shell/input", "project_shell", "input"),
            route("POST", "/api/shell/resize", "project_shell", "resize"),
            route("POST", "/api/shell/stop", "project_shell", "stop"),
            route("GET", "/api/shell/events", "project_shell", "events"),
        ),
        capabilities=frozenset({"shell", "terminal"}),
        state_namespace="project_shell",
    )

