"""Recent project capability module declaration."""

from __future__ import annotations

from http import HTTPStatus

from electroboy.service.http import JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest
from electroboy.service.recent_projects import (
    RECENT_PROJECT_LIMIT,
    RECENT_PROJECTS_RELATIVE_PATH,
    clear_recent_projects,
    load_recent_projects,
    recent_project_entries,
    recent_projects_path,
    remember_recent_project,
    save_recent_projects,
)

from .common import conflict, route


def _clear(request: RouteRequest) -> ServiceResponse:
    payload = request.body()
    requested_projects = payload.get("projects")
    if "projects" not in payload:
        projects = None
    elif not isinstance(requested_projects, list) or any(
        not isinstance(project, dict)
        or not str(project.get("path") or "").strip()
        for project in requested_projects
    ):
        return JsonResponse(
            {"error": "projects must be a list of recent project entries"},
            status=HTTPStatus.BAD_REQUEST,
        )
    else:
        projects = requested_projects
    try:
        clear_recent_projects(request.config.state_root, projects)
        result = {
            **request.services.contexts.project_payload(request.context_id),
            "status": "cleared",
        }
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


_HANDLERS = {"clear": _clear}


def module() -> ServiceModule:
    return ServiceModule(
        id="recent_projects",
        label="Recent Projects",
        routes=(
            route("POST", "/api/recent-projects/clear", "recent_projects", "clear"),
        ),
        handlers=_HANDLERS,
        capabilities=frozenset({"recent-projects"}),
        state_namespace="recent_projects",
    )
