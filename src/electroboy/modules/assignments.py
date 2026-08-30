"""Assignments pane capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule


def module() -> ServiceModule:
    return ServiceModule(
        id="assignments",
        label="Assignments",
        assets=("js/modules/assignments.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset(
            {
                "route-backed-assignments-pane",
                "workspace-companion-pane",
            }
        ),
        state_namespace="assignments",
    )
