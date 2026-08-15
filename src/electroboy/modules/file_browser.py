"""File browser capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="file_browser",
        label="File Browser",
        routes=(
            route("GET", "/file-browser", "file_browser", "window"),
            route("GET", "/api/files/browse", "file_browser", "browse"),
        ),
        capabilities=frozenset({"directory-picker", "file-picker"}),
        state_namespace="file_browser",
    )

