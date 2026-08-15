"""HTTP endpoints owned by the software-engineering workflow."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from typing import Any

from electroboy.service.registry import RouteDefinition, RouteHandler
from electroboy.service.routes import RouteRequest


def _route(method: str, path: str, name: str) -> RouteDefinition:
    return RouteDefinition(method, path, "software", name)


def _error(
    request: RouteRequest,
    error: Exception,
    status: HTTPStatus = HTTPStatus.CONFLICT,
) -> None:
    request.send_json({"error": str(error)}, status=status)


def _state_action(
    request: RouteRequest,
    action: Callable[[], dict[str, object]],
) -> None:
    try:
        payload = action()
    except Exception as error:
        _error(request, error)
        return
    request.send_json(payload)


def _meta_action(request: RouteRequest, method: str) -> None:
    try:
        payload = request.body()
        value = payload.get("repository") or payload.get("path") or ""
        if method in {"create_meta_project", "add_meta_repository"}:
            value = payload.get("path") or ""
        result = getattr(request.state, method)(request.context_id, str(value))
    except Exception as error:
        _error(request, error)
        return
    request.send_json(result)


def _meta_init(request: RouteRequest) -> None:
    _meta_action(request, "create_meta_project")


def _meta_add(request: RouteRequest) -> None:
    _meta_action(request, "add_meta_repository")


def _meta_start(request: RouteRequest) -> None:
    _meta_action(request, "start_meta_repository")


def _meta_remove(request: RouteRequest) -> None:
    _meta_action(request, "remove_meta_repository")


def _create_collection(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.create_feature_collection(
            request.context_id,
            str(payload.get("name") or ""),
        )
    except Exception as error:
        _error(request, error)
        return
    request.send_json(result)


def _switch_collection(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.switch_feature_collection(
            request.context_id,
            str(payload.get("collection_id") or ""),
        )
    except Exception as error:
        _error(request, error)
        return
    request.send_json(result)


def _start_feature(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.start_feature_work_item(
            request.context_id,
            title=str(payload.get("title") or ""),
            feature_name=str(payload.get("name") or "") or None,
            collection_id=str(payload.get("collection_id") or "") or None,
            parent_slug=str(payload.get("parent_slug") or "") or None,
            branch=bool(payload.get("branch")),
            stash_subrepo_changes=bool(payload.get("stash_subrepo_changes")),
        )
    except Exception as error:
        request.send_json(
            request.operation("work_item_error_payload", error),
            status=HTTPStatus.CONFLICT,
        )
        return
    request.send_json(result)


def _switch_feature(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.switch_feature_work_item(
            request.context_id,
            str(payload.get("slug") or ""),
        )
    except Exception as error:
        _error(request, error)
        return
    request.send_json(result)


def _start_bug(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.start_bug_work_item(
            request.context_id,
            issue_reference=str(payload.get("issue_reference") or ""),
            branch=bool(payload.get("branch")),
            stash_subrepo_changes=bool(payload.get("stash_subrepo_changes")),
        )
    except Exception as error:
        request.send_json(
            request.operation("work_item_error_payload", error),
            status=HTTPStatus.CONFLICT,
        )
        return
    request.send_json(result)


def _switch_bug(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.switch_bug_work_item(
            request.context_id,
            str(payload.get("slug") or ""),
        )
    except Exception as error:
        _error(request, error)
        return
    request.send_json(result)


def _agent_started(
    request: RouteRequest,
    start: Callable[[], tuple[Any, bool]],
    label: str,
    *,
    restarted: bool = False,
    include_session_id: bool = False,
) -> None:
    try:
        session, started = start()
        payload = {
            **request.state.project_payload(request.context_id),
            "status": "restarted" if restarted else (
                "started" if started else "running"
            ),
            "command": session.command,
        }
        if include_session_id:
            payload["session_id"] = session.session_id
    except OSError as error:
        _error(
            request,
            RuntimeError(f"could not start {label}: {error}"),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    except Exception as error:
        _error(request, error)
        return
    request.send_json(payload)


def _ad_hoc_start(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.start_ad_hoc_agent(request.context_id),
        "ad-hoc agent",
        include_session_id=True,
    )


def _requirements_start(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.start_requirements_agent(request.context_id),
        "requirements agent",
    )


def _requirements_restart(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.restart_requirements_agent(request.context_id),
        "requirements agent",
        restarted=True,
    )


def _design_start(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.start_design_agent(request.context_id),
        "design agent",
    )


def _design_restart(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.restart_design_agent(request.context_id),
        "design agent",
        restarted=True,
    )


def _design_review_start(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.start_design_review_agent(request.context_id),
        "design review",
    )


def _design_review_start_interactive(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.start_design_review_agent(
            request.context_id,
            interactive=True,
        ),
        "interactive design review",
    )


def _design_review_restart(request: RouteRequest) -> None:
    _agent_started(
        request,
        lambda: request.state.restart_design_review_agent(request.context_id),
        "design review",
        restarted=True,
    )


def _documentation_start(request: RouteRequest) -> None:
    try:
        payload = request.body()
    except ValueError as error:
        _error(request, error, HTTPStatus.BAD_REQUEST)
        return
    _agent_started(
        request,
        lambda: request.state.start_documentation_agent(
            request.context_id,
            interactive=True,
            target=str(payload.get("target") or ""),
        ),
        "documentation agent",
        include_session_id=True,
    )


def _simple_state_handler(method: str, **kwargs: object) -> RouteHandler:
    def handle(request: RouteRequest) -> None:
        _state_action(
            request,
            lambda: getattr(request.state, method)(request.context_id, **kwargs),
        )

    return handle


def _session_for(request: RouteRequest, method: str, missing: str):
    try:
        session = getattr(request.state, method)(request.context_id)
    except Exception as error:
        _error(request, error)
        return None
    if session is None:
        _error(request, RuntimeError(missing))
        return None
    return session


def _session_message(request: RouteRequest, method: str, missing: str) -> None:
    session = _session_for(request, method, missing)
    if session is None:
        return
    try:
        payload = request.body()
        message = str(payload.get("message") or "")
        if not message.strip():
            _error(request, ValueError("message is empty"), HTTPStatus.BAD_REQUEST)
            return
        session.send(message)
    except ValueError as error:
        _error(request, error, HTTPStatus.BAD_REQUEST)
        return
    except Exception as error:
        _error(request, error)
        return
    request.send_json({"status": "sent"})


def _session_events(request: RouteRequest, method: str, missing: str) -> None:
    session = _session_for(request, method, missing)
    if session is not None:
        request.stream_session_events(session)


def _interrupt(request: RouteRequest, method: str) -> None:
    try:
        getattr(request.state, method)(request.context_id)
    except Exception as error:
        _error(request, error)
        return
    request.send_json({"status": "interrupted"})


def _resize(request: RouteRequest, method: str) -> None:
    try:
        payload = request.body()
        getattr(request.state, method)(
            request.context_id,
            int(payload.get("columns") or 120),
            int(payload.get("rows") or 32),
        )
    except Exception as error:
        _error(request, error)
        return
    request.send_json({"status": "resized"})


def _requirements_message(request: RouteRequest) -> None:
    _session_message(
        request,
        "current_requirements_session",
        "requirements agent has not been started",
    )


def _requirements_events(request: RouteRequest) -> None:
    _session_events(
        request,
        "current_requirements_session",
        "requirements agent has not been started",
    )


def _requirements_interrupt(request: RouteRequest) -> None:
    _interrupt(request, "interrupt_requirements_agent")


def _requirements_resize(request: RouteRequest) -> None:
    _resize(request, "resize_requirements_agent")


def _design_message(request: RouteRequest) -> None:
    _session_message(
        request,
        "current_design_session",
        "design agent has not been started",
    )


def _design_events(request: RouteRequest) -> None:
    _session_events(
        request,
        "current_design_session",
        "design agent has not been started",
    )


def _design_interrupt(request: RouteRequest) -> None:
    _interrupt(request, "interrupt_design_agent")


def _design_resize(request: RouteRequest) -> None:
    _resize(request, "resize_design_agent")


def _design_review_events(request: RouteRequest) -> None:
    _session_events(
        request,
        "current_design_review_session",
        "design review has not been started",
    )


def _design_review_interrupt(request: RouteRequest) -> None:
    _interrupt(request, "interrupt_design_review_agent")


def _design_review_resize(request: RouteRequest) -> None:
    _resize(request, "resize_design_review_agent")


ROUTES = (
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
)


HANDLERS: dict[str, RouteHandler] = {
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
    "requirements_complete": _simple_state_handler("complete_requirements_agent"),
    "requirements_skip": _simple_state_handler(
        "approve_requirements",
        skip_approval=True,
    ),
    "requirements_approve": _simple_state_handler("approve_requirements"),
    "requirements_message": _requirements_message,
    "requirements_interrupt": _requirements_interrupt,
    "requirements_resize": _requirements_resize,
    "requirements_events": _requirements_events,
    "design_start": _design_start,
    "design_restart": _design_restart,
    "design_complete": _simple_state_handler("complete_design_agent"),
    "design_message": _design_message,
    "design_interrupt": _design_interrupt,
    "design_resize": _design_resize,
    "design_events": _design_events,
    "design_review_start": _design_review_start,
    "design_review_start_interactive": _design_review_start_interactive,
    "design_review_restart": _design_review_restart,
    "design_review_stop": _simple_state_handler("stop_design_review_agent"),
    "design_review_complete": _simple_state_handler("complete_design_review_agent"),
    "design_review_approve": _simple_state_handler("approve_design"),
    "design_review_skip": _simple_state_handler("approve_design", skip_approval=True),
    "design_review_interrupt": _design_review_interrupt,
    "design_review_resize": _design_review_resize,
    "design_review_events": _design_review_events,
    "documentation_start": _documentation_start,
}
