"""HTTP endpoints owned by the Code Learner workflow."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus

from electroboy.service.http import JsonResponse, ServiceResponse
from electroboy.service.registry import RouteDefinition, RouteHandler
from electroboy.service.routes import RouteRequest

from .controller import (
    CodeLearnerWorkflowController,
    context_options_from_payload,
)


def _route(method: str, path: str, name: str) -> RouteDefinition:
    return RouteDefinition(method, path, "code-learner", name)


def _error(
    error: Exception,
    status: HTTPStatus = HTTPStatus.CONFLICT,
) -> JsonResponse:
    return JsonResponse({"error": str(error)}, status=status)


def _controller(request: RouteRequest) -> CodeLearnerWorkflowController:
    return request.services.workflows.controller(
        "code-learner",
        CodeLearnerWorkflowController,
    )


def _workflow_action(
    action: Callable[[], dict[str, object]],
) -> ServiceResponse:
    try:
        payload = action()
    except Exception as error:
        return _error(error)
    return JsonResponse(payload)


def _open_project(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).open_project(
            request.context_id,
            str(payload.get("path") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _initialize(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(lambda: _controller(request).initialize(request.context_id))


def _initialization_status(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).initialization_status(request.context_id)
    )


def _analysis(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(lambda: _controller(request).analysis(request.context_id))


def _source(request: RouteRequest) -> ServiceResponse:
    try:
        path = str((request.params.get("path") or [""])[0])
        start_line = _optional_query_int(request, "start_line")
        end_line = _optional_query_int(request, "end_line")
        padding = _optional_query_int(request, "padding")
        payload = _controller(request).source_file(
            request.context_id,
            path,
            start_line=start_line,
            end_line=end_line,
            padding=padding if padding is not None else 80,
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(payload)


def _modules(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(lambda: _controller(request).modules(request.context_id))


def _symbols(request: RouteRequest) -> ServiceResponse:
    query = str((request.params.get("query") or [""])[0])
    return _workflow_action(
        lambda: _controller(request).symbols(request.context_id, query)
    )


def _create_walkthrough(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).create_walkthrough(
            request.context_id,
            learning_mode=str(payload.get("learning_mode") or ""),
            target=str(payload.get("target") or ""),
            intended_audience=str(payload.get("intended_audience") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _set_current_step(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).set_current_step(
            request.context_id,
            str(payload.get("walkthrough_id") or ""),
            str(payload.get("step_id") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _learner_context(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).learner_context(
            request.context_id,
            str(payload.get("walkthrough_id") or ""),
            **context_options_from_payload(payload),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _question(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).prepare_question(
            request.context_id,
            str(payload.get("question") or ""),
            str(payload.get("walkthrough_id") or ""),
            **context_options_from_payload(payload),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _start_agent(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        session, started = _controller(request).start_agent(
            request.context_id,
            str(payload.get("walkthrough_id") or ""),
            **context_options_from_payload(payload),
        )
        result = {
            **request.services.contexts.project_payload(request.context_id),
            "status": "started" if started else "running",
            "command": session.command,
            "session_id": session.session_id,
        }
    except OSError as error:
        return _error(
            RuntimeError(f"could not start Code Learner agent: {error}"),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _optional_query_int(request: RouteRequest, name: str) -> int | None:
    values = request.params.get(name) or []
    if not values or values[0] == "":
        return None
    return int(values[0])


ROUTES = (
    _route("POST", "/api/code-learner/project/open", "open_project"),
    _route("POST", "/api/code-learner/init", "initialize"),
    _route("GET", "/api/code-learner/init/status", "initialization_status"),
    _route("GET", "/api/code-learner/analysis", "analysis"),
    _route("GET", "/api/code-learner/source", "source"),
    _route("GET", "/api/code-learner/modules", "modules"),
    _route("GET", "/api/code-learner/symbols", "symbols"),
    _route("POST", "/api/code-learner/walkthrough", "create_walkthrough"),
    _route("POST", "/api/code-learner/walkthrough/step", "set_current_step"),
    _route("POST", "/api/code-learner/context", "learner_context"),
    _route("POST", "/api/code-learner/question", "question"),
    _route("POST", "/api/code-learner/agent/start", "start_agent"),
)

HANDLERS: dict[str, RouteHandler] = {
    "open_project": _open_project,
    "initialize": _initialize,
    "initialization_status": _initialization_status,
    "analysis": _analysis,
    "source": _source,
    "modules": _modules,
    "symbols": _symbols,
    "create_walkthrough": _create_walkthrough,
    "set_current_step": _set_current_step,
    "learner_context": _learner_context,
    "question": _question,
    "start_agent": _start_agent,
}
