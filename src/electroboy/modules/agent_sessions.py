"""Agent session capability module declaration."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus

from electroboy.service.http import (
    BinaryResponse,
    JsonResponse,
    ServiceResponse,
    StreamResponse,
    TextResponse,
)
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import conflict, route
from .progress_service import _session_events_markdown, _session_export_filename


def _selected_session(request: RouteRequest):
    session_id = str((request.params.get("session_id") or [""])[0])
    if session_id:
        return request.services.sessions.by_id(request.context_id, session_id)
    return request.services.sessions.selected(request.context_id)


def _list_sessions(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.sessions.payload(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _session_registry(request: RouteRequest) -> JsonResponse:
    return JsonResponse(request.services.sessions.payload(request.context_id))


def _attach(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = request.services.sessions.attach(
            request.context_id,
            str(payload.get("session_id") or ""),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _select(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = request.services.sessions.select(
            request.context_id,
            str(payload.get("session_id") or ""),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _message(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        message = str(payload.get("message") or "")
        if not message.strip():
            return JsonResponse(
                {"error": "message is empty"},
                status=HTTPStatus.BAD_REQUEST,
            )
        session_id = str(payload.get("session_id") or "")
        if session_id:
            request.services.sessions.send_message(
                request.context_id,
                session_id,
                message,
            )
        else:
            request.services.sessions.send_selected_message(
                request.context_id,
                message,
            )
    except Exception as error:
        return conflict(error)
    return JsonResponse({"status": "sent"})


def _terminal_input(
    request: RouteRequest,
    field: str,
    selected_action: Callable[[str, str], None],
    session_action: Callable[[str, str, str], None],
) -> ServiceResponse:
    try:
        payload = request.body()
        value = str(payload.get(field) or "")
        if not value:
            return JsonResponse(
                {"error": f"{field} is required"},
                status=HTTPStatus.BAD_REQUEST,
            )
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            session_action(request.context_id, session_id, value)
        else:
            selected_action(request.context_id, value)
    except Exception as error:
        return conflict(error)
    return JsonResponse({"status": "sent"})


def _key(request: RouteRequest) -> ServiceResponse:
    return _terminal_input(
        request,
        "key",
        request.services.sessions.send_selected_key,
        request.services.sessions.send_key,
    )


def _raw(request: RouteRequest) -> ServiceResponse:
    return _terminal_input(
        request,
        "data",
        request.services.sessions.send_selected_raw,
        request.services.sessions.send_raw,
    )


def _interrupt(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            request.services.sessions.interrupt(request.context_id, session_id)
        else:
            request.services.sessions.interrupt_selected(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse({"status": "interrupted"})


def _resize(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        columns = int(payload.get("columns") or 120)
        rows = int(payload.get("rows") or 32)
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            request.services.sessions.resize(
                request.context_id,
                session_id,
                columns,
                rows,
            )
        else:
            request.services.sessions.resize_selected(
                request.context_id,
                columns,
                rows,
            )
    except Exception as error:
        return conflict(error)
    return JsonResponse({"status": "resized"})


def _events(request: RouteRequest) -> ServiceResponse:
    try:
        session = _selected_session(request)
    except Exception as error:
        return conflict(error)
    if session is None:
        return JsonResponse(
            {"error": "no agent session is selected"},
            status=HTTPStatus.CONFLICT,
        )
    return StreamResponse(lambda: request.stream_session_events(session))


def _export(request: RouteRequest) -> ServiceResponse:
    try:
        session = _selected_session(request)
    except Exception as error:
        return TextResponse(str(error), status=HTTPStatus.CONFLICT)
    if session is None:
        return TextResponse(
            "no agent session is selected",
            status=HTTPStatus.CONFLICT,
        )
    return BinaryResponse(
        _session_events_markdown(session).encode("utf-8"),
        "text/markdown; charset=utf-8",
        filename=_session_export_filename(session),
    )


_HANDLERS = {
    "list_sessions": _list_sessions,
    "session_registry": _session_registry,
    "attach": _attach,
    "select": _select,
    "message": _message,
    "key": _key,
    "raw": _raw,
    "interrupt": _interrupt,
    "resize": _resize,
    "events": _events,
    "export": _export,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="agent_sessions",
        label="Agent Sessions",
        routes=(
            route("GET", "/api/sessions", "agent_sessions", "list_sessions"),
            route("GET", "/api/session-registry", "agent_sessions", "session_registry"),
            route("POST", "/api/sessions/attach", "agent_sessions", "attach"),
            route("POST", "/api/sessions/select", "agent_sessions", "select"),
            route("POST", "/api/sessions/message", "agent_sessions", "message"),
            route("POST", "/api/sessions/key", "agent_sessions", "key"),
            route("POST", "/api/sessions/raw", "agent_sessions", "raw"),
            route("POST", "/api/sessions/interrupt", "agent_sessions", "interrupt"),
            route("POST", "/api/sessions/resize", "agent_sessions", "resize"),
            route("GET", "/api/sessions/events", "agent_sessions", "events"),
            route("GET", "/api/sessions/export", "agent_sessions", "export"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/agent-sessions.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"terminal", "sse", "transcript-export"}),
        state_namespace="sessions",
    )
