"""Recent project capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule
from electroboy.service.recent_projects import (
    RECENT_PROJECT_LIMIT,
    RECENT_PROJECTS_RELATIVE_PATH,
    load_recent_projects,
    recent_project_entries,
    recent_projects_path,
    remember_recent_project,
    save_recent_projects,
)


def module() -> ServiceModule:
    return ServiceModule(
        id="recent_projects",
        label="Recent Projects",
        capabilities=frozenset({"recent-projects"}),
        state_namespace="recent_projects",
    )
