"""Progress streaming capability module declaration."""

from __future__ import annotations

from http import HTTPStatus

from electroboy.service.http import (
    BinaryResponse,
    ServiceResponse,
    StreamResponse,
    TextResponse,
)
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route
from .progress_service import (
    _progress_export_filename,
    _progress_snapshot,
    _progress_snapshot_markdown,
)


def _events(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.command_root_for(request.context_id)
    except Exception as error:
        return TextResponse(str(error), status=HTTPStatus.CONFLICT)
    return StreamResponse(
        lambda: request.stream_progress_events(
            request.context_id,
            root,
            _progress_snapshot,
        )
    )


def _export(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.command_root_for(request.context_id)
        text, ok = _progress_snapshot(root)
    except Exception as error:
        return TextResponse(str(error), status=HTTPStatus.CONFLICT)
    return BinaryResponse(
        _progress_snapshot_markdown(root, text, ok).encode("utf-8"),
        "text/markdown; charset=utf-8",
        filename=_progress_export_filename(),
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
