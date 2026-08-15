"""Project shell capability module declaration."""

from __future__ import annotations

from http import HTTPStatus

from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route, send_conflict


def _start(request: RouteRequest) -> None:
    try:
        session, started = request.state.start_project_shell(request.context_id)
        payload = {
            **request.state.project_payload(request.context_id),
            "status": "started" if started else "already running",
            "shell_session": session.payload(selected=False),
        }
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(payload)


def _events(request: RouteRequest) -> None:
    try:
        session = request.state.current_project_shell_session(request.context_id)
    except Exception as error:
        send_conflict(request, error)
        return
    if session is None:
        request.send_json(
            {"error": "project shell has not been started"},
            status=HTTPStatus.CONFLICT,
        )
        return
    request.stream_session_events(session)


def _input(request: RouteRequest) -> None:
    try:
        payload = request.body()
        request.state.send_project_shell_input(
            request.context_id,
            str(payload.get("data") or ""),
        )
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json({"status": "sent"})


def _resize(request: RouteRequest) -> None:
    try:
        payload = request.body()
        request.state.resize_project_shell(
            request.context_id,
            int(payload.get("columns") or 120),
            int(payload.get("rows") or 32),
        )
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json({"status": "resized"})


def _stop(request: RouteRequest) -> None:
    try:
        payload = request.state.stop_project_shell(request.context_id)
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(payload)


_HANDLERS = {
    "start": _start,
    "input": _input,
    "resize": _resize,
    "stop": _stop,
    "events": _events,
}


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
        handlers=_HANDLERS,
        assets=("js/modules/project-shell.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"shell", "terminal"}),
        state_namespace="project_shell",
    )
