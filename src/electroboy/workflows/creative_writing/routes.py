"""HTTP endpoints owned by the creative-writing workflow."""

from __future__ import annotations

from http import HTTPStatus

from electroboy.service.http import JsonResponse, ServiceResponse
from electroboy.service.registry import RouteDefinition, RouteHandler
from electroboy.service.routes import RouteRequest


def _route(method: str, path: str, name: str) -> RouteDefinition:
    return RouteDefinition(method, path, "creative-writing", name)


def _error(error: Exception) -> JsonResponse:
    return JsonResponse({"error": str(error)}, status=HTTPStatus.CONFLICT)


def _project_action(request: RouteRequest, method: str) -> ServiceResponse:
    try:
        payload = request.body()
        result = getattr(request.state, method)(
            request.context_id,
            str(payload.get("path") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _open_project(request: RouteRequest) -> ServiceResponse:
    return _project_action(request, "open_creative_project")


def _create_project(request: RouteRequest) -> ServiceResponse:
    return _project_action(request, "create_creative_project")


def _initialize(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.state.initialize_creative_workspace(request.context_id)
    except Exception as error:
        return _error(error)
    return JsonResponse(payload)


def _scratch(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.state.creative_scratchpad(request.context_id)
    except Exception as error:
        return _error(error)
    return JsonResponse(payload)


def _save_scratch(request: RouteRequest) -> ServiceResponse:
    try:
        body = request.body()
        payload = request.state.save_creative_scratchpad(
            request.context_id,
            str(body.get("markdown") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(payload)


def _start_agent(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        active_target = payload.get("active_target")
        session, started = request.state.start_creative_writing_agent(
            request.context_id,
            active_document=str(payload.get("active_document") or ""),
            active_target=(
                active_target if isinstance(active_target, dict) else None
            ),
        )
        result = {
            **request.state.project_payload(request.context_id),
            "status": "started" if started else "running",
            "command": session.command,
            "session_id": session.session_id,
        }
    except OSError as error:
        return JsonResponse(
            {"error": f"could not start creative writing agent: {error}"},
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


ROUTES = (
    _route("POST", "/api/creative/project/open", "open_project"),
    _route("POST", "/api/creative/project/new", "create_project"),
    _route("POST", "/api/creative/init", "initialize"),
    _route("GET", "/api/creative/scratch", "scratch"),
    _route("POST", "/api/creative/scratch", "save_scratch"),
    _route("POST", "/api/creative/agent/start", "start_agent"),
)

HANDLERS: dict[str, RouteHandler] = {
    "open_project": _open_project,
    "create_project": _create_project,
    "initialize": _initialize,
    "scratch": _scratch,
    "save_scratch": _save_scratch,
    "start_agent": _start_agent,
}
