"""Agent session capability module declaration."""

from __future__ import annotations

from http import HTTPStatus

from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route, send_conflict
from .progress_service import _session_events_markdown, _session_export_filename


def _selected_session(request: RouteRequest):
    session_id = str((request.params.get("session_id") or [""])[0])
    if session_id:
        return request.state.session_by_id(request.context_id, session_id)
    return request.state.selected_session(request.context_id)


def _list_sessions(request: RouteRequest) -> None:
    try:
        payload = request.state.session_payload(request.context_id)
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(payload)


def _session_registry(request: RouteRequest) -> None:
    request.send_json(request.state.session_registry_payload())


def _attach(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.attach_session(
            request.context_id,
            str(payload.get("session_id") or ""),
        )
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(result)


def _message(request: RouteRequest) -> None:
    try:
        payload = request.body()
        message = str(payload.get("message") or "")
        if not message.strip():
            request.send_json(
                {"error": "message is empty"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        session_id = str(payload.get("session_id") or "")
        if session_id:
            request.state.send_session_message(
                request.context_id,
                session_id,
                message,
            )
        else:
            request.state.send_selected_session_message(request.context_id, message)
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json({"status": "sent"})


def _terminal_input(request: RouteRequest, field: str, method: str) -> None:
    try:
        payload = request.body()
        value = str(payload.get(field) or "")
        if not value:
            request.send_json(
                {"error": f"{field} is required"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        getattr(request.state, method)(request.context_id, value)
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json({"status": "sent"})


def _key(request: RouteRequest) -> None:
    _terminal_input(request, "key", "send_selected_session_key")


def _raw(request: RouteRequest) -> None:
    _terminal_input(request, "data", "send_selected_session_raw")


def _interrupt(request: RouteRequest) -> None:
    try:
        request.state.interrupt_selected_session(request.context_id)
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json({"status": "interrupted"})


def _resize(request: RouteRequest) -> None:
    try:
        payload = request.body()
        columns = int(payload.get("columns") or 120)
        rows = int(payload.get("rows") or 32)
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            request.state.resize_session(
                request.context_id,
                session_id,
                columns,
                rows,
            )
        else:
            request.state.resize_selected_session(request.context_id, columns, rows)
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json({"status": "resized"})


def _events(request: RouteRequest) -> None:
    try:
        session = _selected_session(request)
    except Exception as error:
        send_conflict(request, error)
        return
    if session is None:
        request.send_json(
            {"error": "no agent session is selected"},
            status=HTTPStatus.CONFLICT,
        )
        return
    request.stream_session_events(session)


def _export(request: RouteRequest) -> None:
    try:
        session = _selected_session(request)
    except Exception as error:
        request.send_text(str(error), status=HTTPStatus.CONFLICT)
        return
    if session is None:
        request.send_text(
            "no agent session is selected",
            status=HTTPStatus.CONFLICT,
        )
        return
    request.send_download(
        _session_events_markdown(session),
        _session_export_filename(session),
    )


_HANDLERS = {
    "list_sessions": _list_sessions,
    "session_registry": _session_registry,
    "attach": _attach,
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
