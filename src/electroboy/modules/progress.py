"""Progress streaming capability module declaration."""

from __future__ import annotations

from http import HTTPStatus

from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route


def _events(request: RouteRequest) -> None:
    try:
        root = request.state.command_root(request.context_id)
    except Exception as error:
        request.send_json({"error": str(error)}, status=HTTPStatus.CONFLICT)
        return
    request.stream_progress_events(request.context_id, root)


def _export(request: RouteRequest) -> None:
    try:
        root = request.state.command_root(request.context_id)
        text, ok = request.operation("progress_snapshot", root)
    except Exception as error:
        request.send_text(str(error), status=HTTPStatus.CONFLICT)
        return
    request.send_download(
        request.operation("progress_snapshot_markdown", root, text, ok),
        request.operation("progress_export_filename"),
    )


_HANDLERS = {"events": _events, "export": _export}


def module() -> ServiceModule:
    return ServiceModule(
        id="progress",
        label="Progress",
        routes=(
            route("GET", "/api/progress/events", "progress", "events"),
            route("GET", "/api/progress/export", "progress", "export"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/progress.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"progress-stream", "issue-announcements"}),
        state_namespace="progress",
    )
