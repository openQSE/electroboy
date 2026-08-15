"""Progress streaming capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="progress",
        label="Progress",
        routes=(
            route("GET", "/api/progress/events", "progress", "events"),
            route("GET", "/api/progress/export", "progress", "export"),
        ),
        assets=("js/modules/progress.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"progress-stream", "issue-announcements"}),
        state_namespace="progress",
    )
