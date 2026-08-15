"""File browser capability module declaration."""

from __future__ import annotations

from http import HTTPStatus

from electroboy.service.file_browser import (
    browse_directories,
    browse_files,
    browse_markdown_files,
)
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route


def _window(request: RouteRequest) -> None:
    initial_path = (request.params.get("path") or [str(request.state.root)])[0]
    mode = (request.params.get("mode") or ["project"])[0]
    request.send_text(
        request.operation("file_browser_window_html", initial_path, mode),
        "text/html; charset=utf-8",
    )


def _browse(request: RouteRequest) -> None:
    path = (request.params.get("path") or [str(request.state.root)])[0]
    mode = (request.params.get("mode") or ["directory"])[0]
    show_hidden = (request.params.get("hidden") or ["0"])[0] == "1"
    try:
        if mode == "file":
            payload = browse_files(path, show_hidden=show_hidden)
        elif mode == "markdown":
            payload = browse_markdown_files(path, show_hidden=show_hidden)
        else:
            payload = browse_directories(path, show_hidden=show_hidden)
    except Exception as error:
        request.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
        return
    request.send_json(payload)


_HANDLERS = {"window": _window, "browse": _browse}


def module() -> ServiceModule:
    return ServiceModule(
        id="file_browser",
        label="File Browser",
        routes=(
            route("GET", "/file-browser", "file_browser", "window"),
            route("GET", "/api/files/browse", "file_browser", "browse"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/file-browser.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"directory-picker", "file-picker"}),
        state_namespace="file_browser",
    )
