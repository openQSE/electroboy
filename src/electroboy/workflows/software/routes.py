"""HTTP endpoints owned by the software-engineering workflow."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus

from electroboy.service.http import JsonResponse, ServiceResponse, StreamResponse
from electroboy.service.registry import RouteDefinition, RouteHandler
from electroboy.service.routes import RouteRequest
from electroboy.service.sessions import AgentSession

from .domain import GENERIC_STAGE_CONFIG, _work_item_error_payload
from .controller import SoftwareWorkflowController


def _route(method: str, path: str, name: str) -> RouteDefinition:
    return RouteDefinition(method, path, "software", name)


def _error(
    error: Exception,
    status: HTTPStatus = HTTPStatus.CONFLICT,
) -> JsonResponse:
    return JsonResponse({"error": str(error)}, status=status)


def _workflow_action(
    action: Callable[[], dict[str, object]],
) -> ServiceResponse:
    try:
        payload = action()
    except Exception as error:
        return _error(error)
    return JsonResponse(payload)


def _controller(request: RouteRequest) -> SoftwareWorkflowController:
    return request.services.workflows.controller(
        "software",
        SoftwareWorkflowController,
    )


def _meta_action(
    request: RouteRequest,
    action: Callable[[str, str], dict[str, object]],
    *,
    repository: bool = False,
) -> ServiceResponse:
    try:
        payload = request.body()
        field = "repository" if repository else "path"
        result = action(request.context_id, str(payload.get(field) or ""))
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _meta_init(request: RouteRequest) -> ServiceResponse:
    return _meta_action(request, _controller(request).create_meta_project)


def _meta_add(request: RouteRequest) -> ServiceResponse:
    return _meta_action(request, _controller(request).add_meta_repository)


def _meta_start(request: RouteRequest) -> ServiceResponse:
    return _meta_action(
        request,
        _controller(request).start_meta_repository,
        repository=True,
    )


def _meta_remove(request: RouteRequest) -> ServiceResponse:
    return _meta_action(
        request,
        _controller(request).remove_meta_repository,
        repository=True,
    )


def _project_action(
    request: RouteRequest,
    action: Callable[[str, str], dict[str, object]],
) -> ServiceResponse:
    try:
        payload = request.body()
        result = action(request.context_id, str(payload.get("path") or ""))
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _open_project(request: RouteRequest) -> ServiceResponse:
    return _project_action(request, _controller(request).open_project)


def _create_project(request: RouteRequest) -> ServiceResponse:
    return _project_action(request, _controller(request).create_project)


def _create_collection(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).create_feature_collection(
            request.context_id,
            str(payload.get("name") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _switch_collection(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).switch_feature_collection(
            request.context_id,
            str(payload.get("collection_id") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _start_feature(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).start_feature_work_item(
            request.context_id,
            title=str(payload.get("title") or ""),
            feature_name=str(payload.get("name") or "") or None,
            collection_id=str(payload.get("collection_id") or "") or None,
            parent_slug=str(payload.get("parent_slug") or "") or None,
            branch=bool(payload.get("branch")),
            stash_subrepo_changes=bool(payload.get("stash_subrepo_changes")),
        )
    except Exception as error:
        return JsonResponse(
            _work_item_error_payload(error),
            status=HTTPStatus.CONFLICT,
        )
    return JsonResponse(result)


def _switch_feature(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).switch_feature_work_item(
            request.context_id,
            str(payload.get("slug") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _start_bug(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).start_bug_work_item(
            request.context_id,
            issue_reference=str(payload.get("issue_reference") or ""),
            branch=bool(payload.get("branch")),
            stash_subrepo_changes=bool(payload.get("stash_subrepo_changes")),
        )
    except Exception as error:
        return JsonResponse(
            _work_item_error_payload(error),
            status=HTTPStatus.CONFLICT,
        )
    return JsonResponse(result)


def _switch_bug(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = _controller(request).switch_bug_work_item(
            request.context_id,
            str(payload.get("slug") or ""),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(result)


def _agent_started(
    request: RouteRequest,
    start: Callable[[], tuple[AgentSession, bool]],
    label: str,
    *,
    restarted: bool = False,
    include_session_id: bool = False,
) -> ServiceResponse:
    try:
        session, started = start()
        payload = {
            **request.services.contexts.project_payload(request.context_id),
            "status": "restarted" if restarted else (
                "started" if started else "running"
            ),
            "command": session.command,
        }
        if include_session_id:
            payload["session_id"] = session.session_id
    except OSError as error:
        return _error(
            RuntimeError(f"could not start {label}: {error}"),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    except Exception as error:
        return _error(error)
    return JsonResponse(payload)


def _ad_hoc_start(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: request.services.sessions.start_ad_hoc(request.context_id),
        "ad-hoc agent",
        include_session_id=True,
    )


def _requirements_start(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: _controller(request).start_requirements_agent(request.context_id),
        "requirements agent",
    )


def _requirements_restart(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: _controller(request).restart_requirements_agent(
            request.context_id
        ),
        "requirements agent",
        restarted=True,
    )


def _design_start(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: _controller(request).start_design_agent(request.context_id),
        "design agent",
    )


def _design_restart(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: _controller(request).restart_design_agent(request.context_id),
        "design agent",
        restarted=True,
    )


def _design_review_start(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: _controller(request).start_design_review_agent(
            request.context_id
        ),
        "design review",
    )


def _design_review_start_interactive(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: _controller(request).start_design_review_agent(
            request.context_id,
            interactive=True,
        ),
        "interactive design review",
    )


def _design_review_restart(request: RouteRequest) -> ServiceResponse:
    return _agent_started(
        request,
        lambda: _controller(request).restart_design_review_agent(
            request.context_id
        ),
        "design review",
        restarted=True,
    )


def _documentation_start(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
    except ValueError as error:
        return _error(error, HTTPStatus.BAD_REQUEST)
    return _agent_started(
        request,
        lambda: _controller(request).start_documentation_agent(
            request.context_id,
            interactive=True,
            target=str(payload.get("target") or ""),
        ),
        "documentation agent",
        include_session_id=True,
    )


def _session_for(
    request: RouteRequest,
    kind: str,
    missing: str,
) -> AgentSession:
    session = request.services.sessions.current(request.context_id, kind)
    if session is None:
        raise RuntimeError(missing)
    return session


def _session_message(
    request: RouteRequest,
    kind: str,
    missing: str,
) -> ServiceResponse:
    try:
        session = _session_for(request, kind, missing)
        payload = request.body()
        message = str(payload.get("message") or "")
        if not message.strip():
            return _error(ValueError("message is empty"), HTTPStatus.BAD_REQUEST)
        session.send(message)
    except ValueError as error:
        return _error(error, HTTPStatus.BAD_REQUEST)
    except Exception as error:
        return _error(error)
    return JsonResponse({"status": "sent"})


def _session_events(
    request: RouteRequest,
    kind: str,
    missing: str,
) -> ServiceResponse:
    try:
        session = _session_for(request, kind, missing)
    except Exception as error:
        return _error(error)
    return StreamResponse(lambda: request.stream_session_events(session))


def _interrupt(request: RouteRequest, kind: str) -> ServiceResponse:
    try:
        request.services.sessions.interrupt_kind(request.context_id, kind)
    except Exception as error:
        return _error(error)
    return JsonResponse({"status": "interrupted"})


def _resize(request: RouteRequest, kind: str) -> ServiceResponse:
    try:
        payload = request.body()
        request.services.sessions.resize_kind(
            request.context_id,
            kind,
            int(payload.get("columns") or 120),
            int(payload.get("rows") or 32),
        )
    except Exception as error:
        return _error(error)
    return JsonResponse({"status": "resized"})


def _requirements_message(request: RouteRequest) -> ServiceResponse:
    return _session_message(
        request,
        "requirements",
        "requirements agent has not been started",
    )


def _requirements_events(request: RouteRequest) -> ServiceResponse:
    return _session_events(
        request,
        "requirements",
        "requirements agent has not been started",
    )


def _requirements_interrupt(request: RouteRequest) -> ServiceResponse:
    return _interrupt(request, "requirements")


def _requirements_resize(request: RouteRequest) -> ServiceResponse:
    return _resize(request, "requirements")


def _design_message(request: RouteRequest) -> ServiceResponse:
    return _session_message(
        request,
        "design",
        "design agent has not been started",
    )


def _design_events(request: RouteRequest) -> ServiceResponse:
    return _session_events(
        request,
        "design",
        "design agent has not been started",
    )


def _design_interrupt(request: RouteRequest) -> ServiceResponse:
    return _interrupt(request, "design")


def _design_resize(request: RouteRequest) -> ServiceResponse:
    return _resize(request, "design")


def _design_review_events(request: RouteRequest) -> ServiceResponse:
    return _session_events(
        request,
        "design-review",
        "design review has not been started",
    )


def _design_review_interrupt(request: RouteRequest) -> ServiceResponse:
    return _interrupt(request, "design-review")


def _design_review_resize(request: RouteRequest) -> ServiceResponse:
    return _resize(request, "design-review")


def _requirements_complete(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).complete_requirements_agent(
            request.context_id
        )
    )


def _requirements_skip(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).approve_requirements(
            request.context_id,
            skip_approval=True,
        )
    )


def _requirements_approve(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).approve_requirements(request.context_id)
    )


def _design_complete(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).complete_design_agent(request.context_id)
    )


def _design_review_stop(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).stop_design_review_agent(request.context_id)
    )


def _design_review_complete(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).complete_design_review_agent(
            request.context_id
        )
    )


def _design_review_approve(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).approve_design(request.context_id)
    )


def _design_review_skip(request: RouteRequest) -> ServiceResponse:
    return _workflow_action(
        lambda: _controller(request).approve_design(
            request.context_id,
            skip_approval=True,
        )
    )


def _generic_stage_handler(stage: str, action: str) -> RouteHandler:
    def handler(request: RouteRequest) -> ServiceResponse:
        controller = _controller(request)
        try:
            if action in {"start", "start-interactive", "restart"}:
                if action == "restart":
                    session, _started = controller.restart_workflow_stage_agent(
                        request.context_id,
                        stage,
                    )
                    status = "restarted"
                else:
                    session, started = controller.start_workflow_stage_agent(
                        request.context_id,
                        stage,
                        interactive=(True if action == "start-interactive" else None),
                    )
                    status = "started" if started else "running"
                return JsonResponse(
                    {
                        **request.services.contexts.project_payload(
                            request.context_id
                        ),
                        "status": status,
                        "command": session.command,
                    }
                )
            if action == "stop":
                return JsonResponse(
                    controller.stop_workflow_stage_agent(
                        request.context_id,
                        stage,
                    )
                )
            if action in {"approve", "skip-approval"}:
                return JsonResponse(
                    controller.approve_workflow_stage(
                        request.context_id,
                        stage,
                        skip_approval=action == "skip-approval",
                    )
                )
        except OSError as error:
            return _error(
                RuntimeError(f"could not start {stage}: {error}"),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        except Exception as error:
            return _error(error)
        return JsonResponse({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    return handler


_GENERIC_STAGE_ACTIONS = (
    "start",
    "start-interactive",
    "restart",
    "stop",
    "approve",
    "skip-approval",
)
_GENERIC_ROUTES = tuple(
    _route(
        "POST",
        f"/api/agents/{stage}/{action}",
        f"generic_{stage.replace('-', '_')}_{action.replace('-', '_')}",
    )
    for stage in GENERIC_STAGE_CONFIG
    for action in _GENERIC_STAGE_ACTIONS
)
_GENERIC_HANDLERS = {
    f"generic_{stage.replace('-', '_')}_{action.replace('-', '_')}": (
        _generic_stage_handler(stage, action)
    )
    for stage in GENERIC_STAGE_CONFIG
    for action in _GENERIC_STAGE_ACTIONS
}


ROUTES = (
    _route("POST", "/api/project/open", "open_project"),
    _route("POST", "/api/project/new", "create_project"),
    _route("POST", "/api/meta/init", "meta_init"),
    _route("POST", "/api/meta/add", "meta_add"),
    _route("POST", "/api/meta/start", "meta_start"),
    _route("POST", "/api/meta/remove", "meta_remove"),
    _route("POST", "/api/work-items/collections", "create_collection"),
    _route("POST", "/api/work-items/collections/switch", "switch_collection"),
    _route("POST", "/api/work-items/features", "start_feature"),
    _route("POST", "/api/work-items/features/switch", "switch_feature"),
    _route("POST", "/api/work-items/bugs", "start_bug"),
    _route("POST", "/api/work-items/bugs/switch", "switch_bug"),
    _route("POST", "/api/agents/ad-hoc/start", "ad_hoc_start"),
    _route("POST", "/api/agents/requirements/start", "requirements_start"),
    _route("POST", "/api/agents/requirements/restart", "requirements_restart"),
    _route("POST", "/api/agents/requirements/complete", "requirements_complete"),
    _route("POST", "/api/agents/requirements/skip", "requirements_skip"),
    _route(
        "POST",
        "/api/agents/requirements/skip-approval",
        "requirements_skip",
    ),
    _route("POST", "/api/agents/requirements/approve", "requirements_approve"),
    _route("POST", "/api/agents/requirements/message", "requirements_message"),
    _route(
        "POST",
        "/api/agents/requirements/interrupt",
        "requirements_interrupt",
    ),
    _route("POST", "/api/agents/requirements/resize", "requirements_resize"),
    _route("GET", "/api/agents/requirements/events", "requirements_events"),
    _route("POST", "/api/agents/design/start", "design_start"),
    _route("POST", "/api/agents/design/restart", "design_restart"),
    _route("POST", "/api/agents/design/complete", "design_complete"),
    _route("POST", "/api/agents/design/message", "design_message"),
    _route("POST", "/api/agents/design/interrupt", "design_interrupt"),
    _route("POST", "/api/agents/design/resize", "design_resize"),
    _route("GET", "/api/agents/design/events", "design_events"),
    _route("POST", "/api/agents/design-review/start", "design_review_start"),
    _route(
        "POST",
        "/api/agents/design-review/start-interactive",
        "design_review_start_interactive",
    ),
    _route("POST", "/api/agents/design-review/restart", "design_review_restart"),
    _route("POST", "/api/agents/design-review/stop", "design_review_stop"),
    _route("POST", "/api/agents/design-review/complete", "design_review_complete"),
    _route("POST", "/api/agents/design-review/approve", "design_review_approve"),
    _route(
        "POST",
        "/api/agents/design-review/skip-approval",
        "design_review_skip",
    ),
    _route(
        "POST",
        "/api/agents/design-review/interrupt",
        "design_review_interrupt",
    ),
    _route("POST", "/api/agents/design-review/resize", "design_review_resize"),
    _route("GET", "/api/agents/design-review/events", "design_review_events"),
    _route("POST", "/api/agents/documentation/start", "documentation_start"),
    _route("POST", "/api/agents/design-approve/approve", "design_review_approve"),
) + _GENERIC_ROUTES


HANDLERS: dict[str, RouteHandler] = {
    "open_project": _open_project,
    "create_project": _create_project,
    "meta_init": _meta_init,
    "meta_add": _meta_add,
    "meta_start": _meta_start,
    "meta_remove": _meta_remove,
    "create_collection": _create_collection,
    "switch_collection": _switch_collection,
    "start_feature": _start_feature,
    "switch_feature": _switch_feature,
    "start_bug": _start_bug,
    "switch_bug": _switch_bug,
    "ad_hoc_start": _ad_hoc_start,
    "requirements_start": _requirements_start,
    "requirements_restart": _requirements_restart,
    "requirements_complete": _requirements_complete,
    "requirements_skip": _requirements_skip,
    "requirements_approve": _requirements_approve,
    "requirements_message": _requirements_message,
    "requirements_interrupt": _requirements_interrupt,
    "requirements_resize": _requirements_resize,
    "requirements_events": _requirements_events,
    "design_start": _design_start,
    "design_restart": _design_restart,
    "design_complete": _design_complete,
    "design_message": _design_message,
    "design_interrupt": _design_interrupt,
    "design_resize": _design_resize,
    "design_events": _design_events,
    "design_review_start": _design_review_start,
    "design_review_start_interactive": _design_review_start_interactive,
    "design_review_restart": _design_review_restart,
    "design_review_stop": _design_review_stop,
    "design_review_complete": _design_review_complete,
    "design_review_approve": _design_review_approve,
    "design_review_skip": _design_review_skip,
    "design_review_interrupt": _design_review_interrupt,
    "design_review_resize": _design_review_resize,
    "design_review_events": _design_review_events,
    "documentation_start": _documentation_start,
    **_GENERIC_HANDLERS,
}
