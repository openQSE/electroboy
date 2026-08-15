"""Recent project capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule


def module() -> ServiceModule:
    return ServiceModule(
        id="recent_projects",
        label="Recent Projects",
        capabilities=frozenset({"recent-projects"}),
        state_namespace="recent_projects",
    )

